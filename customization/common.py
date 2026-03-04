import boto3
from time import gmtime, strftime

REGION = "us-east-1"
SAGEMAKER_URL = f"https://api.sagemaker.{REGION}.amazonaws.com"
STS_URL = f"https://sts.{REGION}.amazonaws.com"

APPLICATION_AUTOSCALING_URL = f"https://application-autoscaling.{REGION}.amazonaws.com"

sm_client = boto3.client(service_name='sagemaker', endpoint_url=SAGEMAKER_URL, region_name=REGION)
autoscaling_client = boto3.client('application-autoscaling', endpoint_url=APPLICATION_AUTOSCALING_URL, region_name=REGION)
account_id = boto3.client('sts', endpoint_url=STS_URL).get_caller_identity()['Account']
role = f"arn:aws:iam::{account_id}:role/sagemaker-execution-role"

INSTANCE_TYPES = {
    'dev': 'ml.g5.xlarge',
    'prod': 'ml.g5.4xlarge',
}

MODEL_CONFIGS = {
    's3_model_uri': f's3://{account_id}-sagemaker-models/app/models/intfloat/multilingual-e5-large-instruct',
}


def create_model(image_version):
    model_name = 'docling-serve-' + strftime("%Y-%m-%d-%H-%M-%S", gmtime())

    container = '{}.dkr.ecr.{}.amazonaws.com/docling-sagemaker:{}'.format(account_id, REGION, image_version)

    print('Model name: ' + model_name)
    print('Container image: ' + container)

    container = {
        'Image': container,
        'Environment': {
            'S3_MODEL_URI': MODEL_CONFIGS['s3_model_uri'],
        }
    }

    create_model_response = sm_client.create_model(
        ModelName = model_name,
        ExecutionRoleArn = role,
        Containers = [container])

    print("Model Arn: " + create_model_response['ModelArn'])
    return model_name


# https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sagemaker/client/create_endpoint_config.html
def create_endpoint_config(model_name, instance_type):
    endpoint_config_name = 'docling-serve-' + strftime("%Y-%m-%d-%H-%M-%S", gmtime())
    print('Endpoint config name: ' + endpoint_config_name)

    create_endpoint_config_response = sm_client.create_endpoint_config(
        EndpointConfigName = endpoint_config_name,
        ProductionVariants=[{
            'InferenceAmiVersion': "al2-ami-sagemaker-inference-gpu-3-1",
            'InstanceType': instance_type,
            'InitialInstanceCount': 1,
            'InitialVariantWeight': 1,
            'ModelName': model_name,
            'VariantName': 'AllTraffic'}])

    print("Endpoint config Arn: " + create_endpoint_config_response['EndpointConfigArn'])
    return endpoint_config_name
