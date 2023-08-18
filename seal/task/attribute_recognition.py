import os.path as op
import torch
from torch.utils.data.dataloader import DataLoader
from torch.optim import lr_scheduler

from ..dataset import build_dataset
from ..data import build_pipeline
from ..models import build_model
from ..evaluation import build_evaluation
from ..utils import build_train_util
from . import task
from .task import BaseTask


@task("InstanceAttributeRecognitionTask")
class InstanceAttributeRecognitionTask(BaseTask):

    name: str = "InstanceAttributeRecognitionTask"
    project: str = "InstanceAttributeRecognitionProject"
    
    def prepare(self):
        
        if self.mode not in ["train", "test"]:
            raise ValueError("The InstanceAttributeRecognitionTask's mode must be train or eval")
        
        self.model = build_model(self.model_setting.name)(**self.model_setting.get_settings()).to(self.device)
        self.evaluation = build_evaluation(self.eval_settings.name)(**self.eval_settings.get_settings())
        self.d_weight = self.task_settings.get_settings()['d_weight']
        self.train_util = build_train_util(self.train_settings.name)

        if self.mode == "train":
            
            self.train_transforms = build_pipeline(self.pipeline_setting.name)(
                mode="train", **self.pipeline_setting.get_settings())
            
            self.evalu_transforms = build_pipeline(self.pipeline_setting.name)(
                mode="evalu", **self.pipeline_setting.get_settings())

            self.trainset = build_dataset(self.dataset_setting.name)(
                mode='train', transform=self.train_transforms, **self.dataset_setting.get_settings())
            
            self.valset = build_dataset(self.dataset_setting.name)(
                mode="val", transform=self.evalu_transforms, **self.dataset_setting.get_settings())
            
            self.testset = build_dataset(self.dataset_setting.name)(
                mode="test", transform=self.evalu_transforms, **self.dataset_setting.get_settings())

            try:
                collate_fn = self.trainset.collate_fn
                print("Using dataset collate function")
            except:
                collate_fn = None
                print("Using dataloader default collate function")
            finally:
                pass

            batch_size = self.train_settings.get_settings()["batch_size"]

            trainloader_settings = self.dataset_setting.get_settings()["trainloader"]            

            trainloader_settings.update({
                "dataset": self.trainset, 
                "batch_size": batch_size, 
                "collate_fn": collate_fn
            })

            self.trainloader = DataLoader(**trainloader_settings)

            valloader_settings = self.dataset_setting.get_settings()["valloader"]

            valloader_settings.update({
                "dataset": self.valset, 
                "batch_size": batch_size, 
                "collate_fn": collate_fn
            })
            
            self.valloader = DataLoader(**valloader_settings)

            testloader_settings = self.dataset_setting.get_settings()["testloader"]
            
            testloader_settings.update({
                "dataset":self.testset, 
                "batch_size": batch_size, 
                "collate_fn": collate_fn
            })
            
            self.testloader = DataLoader(**testloader_settings)

        else:

            batch_size = self.eval_settings.get_settings()["batch_size"]

            self.evalu_transforms = build_pipeline(self.pipeline_setting.name)(mode="evalu", **self.pipeline_setting.get_settings())
            
            self.testset = build_dataset(self.dataset_setting.name)(
                mode="test", transform=self.evalu_transforms, **self.dataset_setting.get_settings())

            try:
                collate_fn = self.testset.collate_fn
                print("Using dataset collate function")
            except:
                collate_fn = None
                print("Using dataloader default collate function")
            finally:
                pass
            
            testloader_settings = self.dataset_setting.get_settings()["testloader"]
            
            testloader_settings.update({
                "dataset":self.testset, 
                "batch_size": batch_size, 
                "collate_fn": collate_fn
            })
            
            self.testloader = DataLoader(**testloader_settings)
    

    def train(self):

        optimizer = self.model.get_optimizer()

        scheduler = lr_scheduler.ReduceLROnPlateau(optimizer, 'max', patience=0, factor=0.1, threshold=0)
        
        highest_mAP = 0.
        
        for epoch in range(self.train_settings.get_settings()["epochs"]):
            self.train_util(self.model, self.trainloader, optimizer, epoch, self.train_settings.get_settings()["epochs"], self.device, amp=self.train_settings.get_settings()["amp"])
            self.evaluation(model=self.model, dataloader=self.valloader)
            mAP = self.evaluation.get_mAP()
            res_dict = {"validation_mAP": mAP, "epoch": epoch}
            scheduler.step(res_dict["validation_mAP"])

            if res_dict["validation_mAP"] > highest_mAP:
                highest_mAP = res_dict["validation_mAP"]
                try:
                    weight_name = self.project + "-model-highest.pth"
                    torch.save(self.model.state_dict(), op.join(self.d_weight, weight_name))
                except:
                    print("Save Model Weight Failed!")

        print("Finish Train")

        print("Testing the model of highest validation mAP.")
        weight_name = self.project + "-model-highest.pth"
        state_dict = torch.load(op.join(self.d_weight, weight_name), map_location=self.device)
        self.model.load_state_dict(state_dict)
        self.evaluation(model=self.model, dataloader=self.testloader)
        res_dict = {"test_mAP": mAP}
        print("Finish Test")
        print(res_dict)


    def eval(self):
        
        try:
            weight_name = self.project + "-model-highest.pth"
            print(f"Loading pretrained weight: {weight_name}")
            state_dict = torch.load(op.join(self.d_weight, weight_name), map_location='cpu')

            missing_keys, unexpected_keys = self.model.load_state_dict(state_dict, strict=False)
            print(f"Missing keys: {missing_keys}")
            print(f"Unexpected keys: {unexpected_keys}")
            print("Finish ...")
        except:
            print("Cannot find the weight! Using Initialized Weight")
            
        print("Testing the model of highest validation mAP.")  
        
        self.evaluation(self.testloader, self.model)
        


    def run(self):
        if self.mode == "train":
            self.train()
        else:
            self.eval()